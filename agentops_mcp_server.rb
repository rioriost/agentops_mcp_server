class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/0c/3f/2cf2f5c5ef532b935b0a1316854cd2fe5d23fe7d777482eb21024f3eac63/agentops_mcp_server-0.4.2.tar.gz"
  sha256 "9b25c40dcc63ea4b9cd435d58810f653ac11248fa49eb395fe25a5ae43654636"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
