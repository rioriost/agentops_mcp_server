class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/32/5e/92cc988c00e9e9f2ba425494850664b9453db46b79ccf5e64408b8df2740/agentops_mcp_server-0.4.6.tar.gz"
  sha256 "edc02a473d33ad5669606c92a000c7a9981f9d50473f917882a3ebaa5588da2e"
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
