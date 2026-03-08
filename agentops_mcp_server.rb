class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/97/12/32ace54e2761847ec1d368849abd81f5c5c8854f8c1fc8c9ee60b12dff37/agentops_mcp_server-0.4.5.tar.gz"
  sha256 "948f43287fe95cf0ddc3fd71303b8ea7ffb014ac84e57a80f271228f14da08d6"
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
