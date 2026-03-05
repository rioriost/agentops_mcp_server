class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/ab/57/285160832514e029de3435c8374d0c018d8adc25a957148fd373582f440b/agentops_mcp_server-0.2.1.tar.gz"
  sha256 "9c7ed117beba46db846947044a616e3eb89a315915696fdf6f4cef6feacec257"
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
